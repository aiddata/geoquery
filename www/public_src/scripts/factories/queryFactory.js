angular.module('aiddataDET')
  .factory('queryFactory', function(ajaxFactory, $log, $q) {

    var datasets = {},
        boundaries = {};

    var query = {};

    function retrieveBoundaries () {
      if (!boundaries.options) {
        return ajaxFactory.boundaries()
          .then(function(results) {
            boundaries.options = results.data.boundaries;
            return boundaries.options;
          });
      }
      $log.debug('Already Defined');
      return boundaries.options;
    }

    function defineBoundary (boundary, subboundary) {
      var b = _.find(boundaries.options, { boundaryId: boundary }),
          sb = _.find(b.subBoundaries, { name: subboundary });

      query.boundary = {
        title: sb.title,
        group: sb.options.group,
        name: sb.name,
        description: sb.description,
        path: sb.base + _.head(sb.resources).path
      };
    }

    return {
      filters: { },

      filterOptions: { },

      getBoundaries: function () {
        return $q.when(retrieveBoundaries())
          .then(function(boundaries) {
            return boundaries;
          });
      },

      setBoundary: function(boundary, subboundary) {
        return $q.when(defineBoundary(boundary, subboundary));
      },

      getDatasets: function (boundary) {
        return ajaxFactory.datasets(boundary)
          .then(function(results) {
            datasets = results.data;
            return datasets;
          }, function(err) {
            $log.error(err);
          });
      },

      updateFilters: function () {
        var self = this;

        return ajaxFactory.filters(self.filters)
          .then(function(results) {
            var filterOptions = self.filterOptions = results.data;
            filterOptions.filterTypes = _.keys(filterOptions.distinct);

            return filterOptions;
          }, function(err) {
            $log.error(err);
          });
      },

      setDataset: function(datasetName) {
        this.filters.dataset = datasetName;
      },

      toggleFilterOn: function(filter, option) {
        if (!this.filters[filter]) {
          this.filters[filter] = [];
        }
        this.filters[filter].push(option);
      },

      toggleFilterOff: function (filter, option) {
        _.pull(this.filters[filter], option);
        if (!this.filters[filter].length) {
          delete this.filters[filter];
        }
      },

      toggleAll: function (filter) {
        delete this.filters[filter];
        return this.filters;
      }
    };
  });
