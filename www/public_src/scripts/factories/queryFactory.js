angular.module('aiddataDET')
  .factory('queryFactory', function(ajaxFactory, $log, $q) {

    var datasets = [],            // All Datasets
        boundaries = {};          // All Boundaries

    var _boundary = {},            // Selected Boundary
        _subBoundary = {};         // Selected Enumeration Units

    var query = {},               // Current Query Object
        cart = [];                // Array of all queries


    function retrieveBoundaries () {
      if (!boundaries.options) {
        return ajaxFactory.boundaries()
          .then(function(results) {
            boundaries.options = results.data.boundaries;
            return boundaries.options;
          });
      }
      $log.debug('Boundaries Already Defined');
      return boundaries.options;
    }

    function retrieveDatasets (boundaryId) {
      if (!datasets.length) {
        return ajaxFactory.datasets(boundaryId)
          .then(function(results) {
            if (!results.data.length) {
              return $q.reject('No Datasets Found');
            }

            datasets = results.data;
            return datasets;
          });
      }
      $log.debug('Datasets Already Defined');
      return datasets;
    }

    function findBoundary (boundaryId) {
      return _.find(boundaries.options, { boundaryId: boundaryId });
    }

    function findSubBoundary(boundary, subboundaryId) {
      return _.find(boundary.subBoundaries, { name: subboundaryId });
    }

    function defineBoundary (boundaryId, subboundaryId) {
      _boundary = findBoundary(boundaryId);
      _subBoundary = findSubBoundary(_boundary, subboundaryId);

      query.boundary = {
        title: _subBoundary.title,
        group: _subBoundary.options.group,
        name: _subBoundary.name,
        description: _subBoundary.description,
        path: _subBoundary.base + _.head(_subBoundary.resources).path
      };
    }

    return {
      filters: { },

      filterOptions: { },

      options: {
        options: { extract_types: [] },
        files: []
      },

      getBoundaries: function () {
        return $q.when(retrieveBoundaries())
          .then(function(boundaries) {
            return boundaries;
          });
      },

      setBoundary: function(boundary, subboundary) {
        return $q.when(defineBoundary(boundary, subboundary));
      },

      getDatasets: function (boundaryId) {
        return $q.when(retrieveDatasets(boundaryId))
        .then(function(datasets) {
          return datasets;
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

      resetFilter: function (filter) {
        delete this.filters[filter];
        return this.filters;
      },

      toggleOptionOn: function (key, val) {
        val.checked = true;
        _.get(this.options, key).push(val);
      },

      toggleOptionOff: function (key, val) {
        val.checked = false;
        _.pull(_.get(this.options, key), val);
      },

      resetOption: function (key) {
        _.chain(this.options)
          .get(key)
          .each(function(val) { val.checked = false; })
          .value()
          .splice(0);
      }
    };
  });
