angular.module('aiddataDET')
  .factory('filterFactory', function(ajaxFactory, $log) {


    return {
      filters: { },

      filterOptions: { },

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
