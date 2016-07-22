angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $log, $state, $stateParams, queryFactory) {
  $scope.filters = queryFactory.filters;
  $scope.options = queryFactory.options;
  $scope.dataset = {};
  $scope.totals = {};
  $scope.queryStructure = {};
  $scope.geography = $stateParams.boundary;
  $scope.requestData = { name: 'New Request', editing: false, canReset: false };

  $scope.removeFilter = function(filter, option) {
    return $scope.dataset.type === 'release' ? queryFactory.toggleFilterOff(filter, option) :
      queryFactory.toggleOptionOff(filter, option);
  };

  $scope.clearFilters = function () {
    _.chain($scope.queryStructure)
      .filter(function(param) {
        return param.optional && param.value && param.value.length;
      })
      .each(function(param) {
        return $scope.dataset.type === 'release' ? queryFactory.resetFilter(param.key) :
          queryFactory.resetOption(param.key);
      })
      .value();
  };

  $rootScope.$on('filters:updated', function(e, data) {
    updateCounts();
    $scope.queryStructure = setQueryStructure();
  });

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
    $scope.queryStructure = setQueryStructure();
  });

  function setQueryStructure () {
    return [
      { value: [ $scope.dataset.title ], pre: 'Extract data from ', optional: false },
      { value: [ $scope.geography ], pre: 'within ', optional: false },
      { value: $scope.filters.donors, pre: 'given by ', optional: true, key: 'donors' },
      { value: $scope.filters.ad_sector_names, pre: 'to promote ', optional: true, key: 'ad_sector_names' },
      { value: $scope.options.options.extract_types, pre: 'calculating', optional: true, key: 'options.extract_types' },
      { value: $scope.options.files, pre: 'using', optional: true, key: 'files' }
    ];
  }

  $scope.addToCart = function() {
    queryFactory.generateQuery()
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  };

  $scope.$on('$viewContentLoaded', function(event) {
    if ($state.params.dataset) {
      $scope.dataset = queryFactory.getDataset();
      $scope.queryStructure = setQueryStructure();
      updateCounts();
    }
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    if (toParams.dataset) {
      $scope.dataset = queryFactory.getDataset(toParams.dataset);
      $scope.queryStructure = setQueryStructure();
    }
  });

  function updateCounts() {
    $scope.totals = _.pick(queryFactory.filterOptions, ['projects', 'locations']);

    $scope.requestData.canReset = _.some($scope.filters, function(d, i) {
      return $scope.dataset.fields[i] && !_.isEqual(d, ['All']);
    });
  }

});
